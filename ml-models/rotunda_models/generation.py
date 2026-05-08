"""Checkpoint loading and constrained generation for cadence models."""

from __future__ import annotations

import math
import random
from pathlib import Path
from typing import Any

import torch

from .constants import (
    CHAR_EOS,
    CHAR_SEP,
    CHAR_UNK,
    KEY_BACKSPACE,
    KEY_STOP,
)
from .keyboard_logic import (
    apply_keyboard_action,
    constrained_keyboard_action,
    keyboard_next_char,
    minimum_terminal_edit_steps,
    terminal_edit_actions,
)
from .models.keyboard import KeyboardActionGRU, decode_press_count_logits
from .models.common import sample_timing_log
from .models.mouse import MouseTrajectoryGRU
from .types import MouseEpisode
from .utils import log_to_dt, screen_position_from_goal_relative


def load_checkpoint(path: Path, device: torch.device) -> dict:
    """Load a training checkpoint onto the requested torch device."""
    return torch.load(path, map_location=device, weights_only=False)


class MouseDecoder:
    """Autoregressive runtime decoder for `MouseTrajectoryGRU` checkpoints."""

    def __init__(
        self,
        model: MouseTrajectoryGRU,
        coordinate_scale: float,
        position_frame: str,
        actions: list[str],
        device: torch.device,
    ):
        self.model = model
        self.coordinate_scale = coordinate_scale
        self.position_frame = position_frame
        self.actions = actions
        self.device = device

    @staticmethod
    def endpoint_step_budget(distance: float, max_steps: int) -> int:
        """Return a realistic endpoint-guidance budget for a point-to-click path."""
        capped_distance = min(max(0.0, float(distance)), 400.0)
        budget = int(round(8.0 + (2.0 * math.sqrt(capped_distance))))
        return max(4, min(max_steps, budget))

    def decode(
        self,
        episode: MouseEpisode,
        max_steps: int,
        click_threshold: float,
        min_dt_ms: float,
        endpoint_guidance: bool = True,
        sample: bool = False,
        temperature: float = 1.0,
        timing_temperature: float = 0.0,
        timing_seed: int | None = None,
        click_at_end: bool = True,
    ) -> list[dict[str, float | str]]:
        """Roll out a complete mouse trajectory before any caller dispatches it."""
        # Mouse generation is an autoregressive rollout conditioned on one concrete
        # target. The model predicts the next delay, movement increment, and action
        # class; endpoint guidance keeps the known target reachable for execution.
        actions = self.actions
        action_count = len(actions)
        bos_index = action_count
        start_x = episode.start_x
        start_y = episode.start_y
        dst_x = episode.dst_x
        dst_y = episode.dst_y
        dx = dst_x - start_x
        dy = dst_y - start_y
        distance = math.hypot(dx, dy)
        endpoint_budget = self.endpoint_step_budget(distance, max_steps)
        scale = max(1.0, float(self.coordinate_scale))
        condition = torch.tensor(
            [[start_x / scale, start_y / scale, dst_x / scale, dst_y / scale, dx / scale, dy / scale, distance / scale]],
            dtype=torch.float32,
            device=self.device,
        )

        offset = 0.0
        state_along = 0.0
        state_perp = 0.0
        rows: list[dict[str, float | str]] = []
        previous_rows: list[list[float]] = [[0.0, 0.0, 0.0] + [0.0] * (action_count + 1)]
        previous_rows[0][3 + bos_index] = 1.0
        timing_generator = None
        if timing_temperature > 0 and timing_seed is not None:
            timing_generator = torch.Generator(device=self.device)
            timing_generator.manual_seed(int(timing_seed))
        with torch.no_grad():
            for step_index in range(max_steps):
                previous = torch.tensor([previous_rows], dtype=torch.float32, device=self.device)
                dt_pred_all, pos_pred_all, logits_all = self.model(condition, previous)
                dt_pred = dt_pred_all[:, -1:]
                pos_pred = pos_pred_all[:, -1:, :]
                logits = logits_all[:, -1:, :]
                if sample:
                    probs = torch.softmax(logits[0, 0] / max(temperature, 1e-4), dim=-1)
                    action_id = int(torch.multinomial(probs, 1).item())
                else:
                    action_id = int(logits[0, 0].argmax().item())
                action = actions[action_id]
                dt_log = sample_timing_log(
                    dt_pred[0, 0],
                    timing_temperature,
                    generator=timing_generator,
                )
                dt_ms = log_to_dt(float(dt_log.cpu()))
                if rows:
                    dt_ms = max(dt_ms, min_dt_ms)
                offset += dt_ms

                rel_x = float(pos_pred[0, 0, 0].cpu())
                rel_y = float(pos_pred[0, 0, 1].cpu())
                if self.position_frame == "goal_relative_delta":
                    if endpoint_guidance:
                        remaining_steps = max(1, endpoint_budget - step_index)
                        min_delta = (1.0 - state_along) / remaining_steps
                        max_delta = max(min_delta, min_delta * 2.0)
                        guided_delta = max(min(rel_x, max_delta), min_delta, 0.0)
                        state_along = min(1.0, state_along + guided_delta)
                        guided_perp = state_perp + rel_y
                        envelope = max(0.0, 0.35 * math.sin(math.pi * max(0.0, min(1.0, state_along))))
                        state_perp = max(-envelope, min(envelope, guided_perp * (1.0 - 0.25 * state_along)))
                        if state_along >= click_threshold:
                            action = "left_click" if click_at_end else "move"
                            action_id = actions.index("left_click") if click_at_end and "left_click" in actions else 0
                            state_along = 1.0
                            state_perp = 0.0
                    else:
                        state_along += rel_x
                        state_perp += rel_y
                    x, y = screen_position_from_goal_relative(start_x, start_y, dst_x, dst_y, state_along, state_perp)
                elif self.position_frame == "goal_relative":
                    state_along = rel_x
                    state_perp = rel_y
                    x, y = screen_position_from_goal_relative(start_x, start_y, dst_x, dst_y, rel_x, rel_y)
                else:
                    x = start_x + rel_x * scale
                    y = start_y + rel_y * scale
                    state_along = rel_x
                    state_perp = rel_y

                terminal = action != "move" or state_along >= click_threshold
                if terminal:
                    x = dst_x
                    y = dst_y
                    if not click_at_end:
                        action = "move"
                        action_id = 0
                rows.append({"offsetMs": offset, "dtMs": dt_ms, "x": x, "y": y, "action": action})
                if terminal:
                    break

                next_previous = [0.0, state_along, state_perp] + [0.0] * (action_count + 1)
                next_previous[0] = float(dt_log.detach().cpu())
                next_previous[3 + action_id] = 1.0
                previous_rows.append(next_previous)

        return rows


def simulate_mouse_click_rows(
    model: MouseTrajectoryGRU,
    episode: MouseEpisode,
    coordinate_scale: float,
    position_frame: str,
    actions: list[str],
    device: torch.device,
    max_steps: int,
    click_threshold: float,
    min_dt_ms: float,
    endpoint_guidance: bool = True,
    sample: bool = False,
    temperature: float = 1.0,
    timing_temperature: float = 0.0,
    timing_seed: int | None = None,
    click_at_end: bool = True,
) -> list[dict[str, float | str]]:
    """Compatibility wrapper around `MouseDecoder.decode`."""
    return MouseDecoder(
        model=model,
        coordinate_scale=coordinate_scale,
        position_frame=position_frame,
        actions=actions,
        device=device,
    ).decode(
        episode,
        max_steps=max_steps,
        click_threshold=click_threshold,
        min_dt_ms=min_dt_ms,
        endpoint_guidance=endpoint_guidance,
        sample=sample,
        temperature=temperature,
        timing_temperature=timing_temperature,
        timing_seed=timing_seed,
        click_at_end=click_at_end,
    )


def encode_keyboard_condition(
    initial_string: str,
    final_string: str,
    char_to_id: dict[str, int],
    device: torch.device,
) -> tuple[torch.Tensor, torch.Tensor]:
    """Encode the initial/final text condition expected by keyboard checkpoints.

    Checkpoints trained after the initial/final contract change include a
    separator token between the starting text and target text. Older checkpoints
    only condition on the target string; this helper preserves both formats and
    returns the token tensor plus its sequence length.
    """
    # Keyboard checkpoints may condition on both the initial and final strings.
    # Newer checkpoints include a separator token; older ones only encoded the
    # final string, so keep that compatibility path while decoding.
    if CHAR_SEP in char_to_id:
        tokens = [*initial_string, CHAR_SEP, *final_string]
    else:
        tokens = list(final_string)
    ids = [char_to_id.get(char, char_to_id[CHAR_UNK]) for char in tokens]
    ids.append(char_to_id[CHAR_EOS])
    return (
        torch.tensor([ids], dtype=torch.long, device=device),
        torch.tensor([len(ids)], dtype=torch.long, device=device),
    )


def encode_final_string(final_string: str, char_to_id: dict[str, int], device: torch.device) -> tuple[torch.Tensor, torch.Tensor]:
    """Encode a keyboard target string for older final-string-only callers."""
    return encode_keyboard_condition("", final_string, char_to_id, device)


def require_keyboard_target_supported(
    initial_string: str,
    final_string: str,
    action_to_id: dict[str, int],
) -> None:
    """Raise if constrained keyboard decoding cannot emit required insertions."""
    missing = sorted(
        {
            action
            for action in terminal_edit_actions(initial_string, final_string)
            if action != KEY_BACKSPACE and action not in action_to_id
        }
    )
    if missing:
        labels = ", ".join(repr(char) for char in missing)
        raise SystemExit(f"Target edit requires characters outside the keyboard action vocabulary: {labels}")


def structured_keyboard_action_ids(
    final_string: str,
    text: list[str],
    action_to_id: dict[str, int],
    remaining_steps_after_action: int,
) -> list[int]:
    """Return keyboard action ids that keep the target reachable.

    The current text is simulated through every candidate action, and the
    candidate is accepted only when the minimum remaining edit distance fits
    inside `remaining_steps_after_action`. This is the hard validity mask used
    by constrained keyboard decoding.
    """
    # Structured decoding masks the model to edits that can still reach the
    # target within the remaining budget. This keeps the rollout useful for
    # execution while leaving the model room to choose repairs or local edits.
    current = "".join(text)
    if current == final_string:
        return [int(action_to_id[KEY_STOP])]

    valid: list[int] = []
    for action, action_id in action_to_id.items():
        if action == KEY_STOP:
            continue
        if action == KEY_BACKSPACE and (not text or final_string.startswith(current)):
            continue
        candidate = list(text)
        apply_keyboard_action(candidate, action)
        if candidate == text:
            continue
        if minimum_terminal_edit_steps(final_string, candidate) <= remaining_steps_after_action:
            valid.append(int(action_id))

    if not valid:
        fallback = constrained_keyboard_action(final_string, text)
        return [int(action_to_id[fallback])]
    return sorted(set(valid))


def choose_structured_keyboard_action(
    logits: torch.Tensor,
    valid_action_ids: list[int],
    id_to_action: dict[int, str],
    sample: bool,
    temperature: float,
    preferred_action_id: int | None = None,
    preferred_bias: float = 0.0,
) -> tuple[str, int]:
    """Select an action from valid ids using model logits and optional sampling.

    `valid_action_ids` is assumed to have already enforced reachability. The
    optional preferred action bias nudges toward a canonical shortest-path edit
    without removing other valid model-preferred actions.
    """
    # The mask is a hard validity constraint, while preferred_bias is a soft
    # nudge toward the shortest canonical edit. Lowering the bias gives the
    # learned action logits more influence without risking unreachable text.
    candidate_ids = torch.tensor(valid_action_ids, dtype=torch.long, device=logits.device)
    candidate_logits = logits.index_select(0, candidate_ids).clone()
    if preferred_action_id is not None and preferred_bias:
        preferred_matches = candidate_ids == int(preferred_action_id)
        candidate_logits = candidate_logits + preferred_matches.float() * float(preferred_bias)
    if sample and len(valid_action_ids) > 1:
        probs = torch.softmax(candidate_logits / max(temperature, 1e-4), dim=0)
        selected_index = int(torch.multinomial(probs, 1).item())
    else:
        selected_index = int(candidate_logits.argmax().item())
    action_id = int(candidate_ids[selected_index].detach().cpu())
    return id_to_action[action_id], action_id


def choose_learned_keyboard_typo(
    typo_logit: torch.Tensor,
    typo_action_logits: torch.Tensor,
    valid_action_ids: list[int],
    id_to_action: dict[int, str],
    preferred_action_id: int,
    rng: random.Random,
    sample: bool,
    temperature: float,
    threshold: float,
) -> tuple[str, int, float] | None:
    """Choose one learned wrong-character action under the structured mask."""
    candidate_ids_list = [
        int(action_id)
        for action_id in valid_action_ids
        if int(action_id) != int(preferred_action_id)
        and id_to_action[int(action_id)] not in {KEY_BACKSPACE, KEY_STOP}
    ]
    if not candidate_ids_list:
        return None

    probability = float(torch.sigmoid(typo_logit).detach().cpu())
    if sample:
        if rng.random() >= probability:
            return None
    elif probability < threshold:
        return None

    candidate_ids = torch.tensor(candidate_ids_list, dtype=torch.long, device=typo_action_logits.device)
    candidate_logits = typo_action_logits.index_select(0, candidate_ids)
    if sample and len(candidate_ids_list) > 1:
        probabilities = torch.softmax(candidate_logits / max(temperature, 1e-4), dim=0).detach().cpu().tolist()
        pick = rng.random()
        cumulative = 0.0
        selected_index = len(candidate_ids_list) - 1
        for index, candidate_probability in enumerate(probabilities):
            cumulative += float(candidate_probability)
            if pick <= cumulative:
                selected_index = index
                break
    else:
        selected_index = int(candidate_logits.argmax().item())
    action_id = int(candidate_ids[selected_index].detach().cpu())
    return id_to_action[action_id], action_id, probability


class KeyboardDecoder:
    """Runtime decoder for `KeyboardActionGRU` checkpoints."""

    def __init__(self, checkpoint: dict, model: KeyboardActionGRU, device: torch.device):
        self.checkpoint = checkpoint
        self.model = model
        self.device = device

    def decode(
        self,
        final_string: str,
        max_steps: int,
        decode_mode: str = "constrained",
        sample: bool = False,
        temperature: float = 1.0,
        initial_string: str = "",
        structured_extra_steps: int = 6,
        canonical_bias: float = 3.0,
        max_typos: int = 2,
        typo_seed: int | None = 13,
        learned_typo_threshold: float = 0.2,
        timing_temperature: float = 0.0,
        timing_seed: int | None = None,
    ) -> list[dict[str, Any]]:
        return _decode_keyboard_rows_impl(
            checkpoint=self.checkpoint,
            model=self.model,
            final_string=final_string,
            device=self.device,
            max_steps=max_steps,
            decode_mode=decode_mode,
            sample=sample,
            temperature=temperature,
            initial_string=initial_string,
            structured_extra_steps=structured_extra_steps,
            canonical_bias=canonical_bias,
            max_typos=max_typos,
            typo_seed=typo_seed,
            learned_typo_threshold=learned_typo_threshold,
            timing_temperature=timing_temperature,
            timing_seed=timing_seed,
        )


def _constrained_keyboard_budget(
    model: KeyboardActionGRU,
    final_ids: torch.Tensor,
    final_lengths: torch.Tensor,
    *,
    final_string: str,
    min_steps: int,
    max_steps: int,
    structured_extra_steps: int,
) -> tuple[int, float | None]:
    """Return the constrained decode budget and optional raw press-count prediction."""
    if model.press_count_head is None:
        raise RuntimeError("Constrained keyboard decode requires a predictive press-count head.")

    with torch.no_grad():
        condition = model.encode(final_ids, final_lengths)
        press_count_logits = model.press_count_head(condition).squeeze(-1)
        predicted_press_count = float(decode_press_count_logits(press_count_logits)[0].detach().cpu())
    if not math.isfinite(predicted_press_count):
        raise RuntimeError("Constrained keyboard decode produced a non-finite press-count prediction.")

    extra_steps = max(0, structured_extra_steps)
    floor_budget = max(min_steps, len(final_string) + extra_steps)
    predicted_budget = max(min_steps, math.ceil(max(0.0, predicted_press_count - 1e-6)))
    return min(max_steps, max(floor_budget, predicted_budget)), predicted_press_count


def _decode_keyboard_rows_impl(
    checkpoint: dict,
    model: KeyboardActionGRU,
    final_string: str,
    device: torch.device,
    max_steps: int,
    decode_mode: str = "constrained",
    sample: bool = False,
    temperature: float = 1.0,
    initial_string: str = "",
    structured_extra_steps: int = 6,
    canonical_bias: float = 3.0,
    max_typos: int = 2,
    typo_seed: int | None = 13,
    learned_typo_threshold: float = 0.2,
    timing_temperature: float = 0.0,
    timing_seed: int | None = None,
) -> list[dict[str, Any]]:
    """Roll out keyboard edit rows from a trained keyboard checkpoint model.

    The returned rows contain cumulative `offsetMs`, per-key `dtMs`, the emitted
    action, resulting text, and a `stepKind` label. `constrained` mode masks the
    model to actions that can still reach `final_string`; `canonical` mode emits
    the shortest valid edit path while still using model timing; `unconstrained`
    mode exposes raw model action choices and may not reach the target. Learned
    typo emission is part of constrained decoding and uses the same reachability
    mask as normal model actions.
    """
    # Keyboard generation has three layers:
    # 1. Encode the requested edit as the model condition.
    # 2. Ask the model for timing and action logits at each step.
    # 3. Optionally constrain those logits so the emitted action sequence remains
    #    executable and reaches the requested final string.
    char_to_id = checkpoint["char_to_id"]
    action_to_id = checkpoint.get("action_to_id")
    id_to_action = {int(index): token for index, token in checkpoint["id_to_action"].items()}
    if action_to_id is None:
        action_to_id = {token: index for index, token in id_to_action.items()}
    action_count = len(id_to_action)
    if max_typos < 0:
        raise ValueError(f"max_typos must be non-negative, got {max_typos}.")
    if not 0.0 <= learned_typo_threshold <= 1.0:
        raise ValueError(f"learned_typo_threshold must be between 0 and 1, got {learned_typo_threshold}.")
    final_ids, final_lengths = encode_keyboard_condition(initial_string, final_string, char_to_id, device)
    predicted_press_count: float | None = None

    # Establish the decode contract up front. Constrained mode uses the learned
    # press budget with a small floor based on target length; canonical mode
    # follows the shortest path; unconstrained mode is raw logits and may miss
    # the target.
    if decode_mode == "constrained":
        require_keyboard_target_supported(initial_string, final_string, action_to_id)
        min_steps = minimum_terminal_edit_steps(final_string, list(initial_string))
        if max_steps < min_steps:
            raise SystemExit(
                f"Constrained keyboard decode needs at least {min_steps} steps for this target; "
                f"got --max-steps {max_steps}."
            )
        effective_max_steps, predicted_press_count = _constrained_keyboard_budget(
            model,
            final_ids,
            final_lengths,
            final_string=final_string,
            min_steps=min_steps,
            max_steps=max_steps,
            structured_extra_steps=structured_extra_steps,
        )
    elif decode_mode == "canonical":
        require_keyboard_target_supported(initial_string, final_string, action_to_id)
        min_steps = minimum_terminal_edit_steps(final_string, list(initial_string))
        effective_max_steps = max_steps
        if max_steps < min_steps:
            raise SystemExit(
                f"Canonical keyboard decode needs at least {min_steps} steps for this target; "
                f"got --max-steps {max_steps}."
            )
    elif decode_mode != "unconstrained":
        raise ValueError(f"Unknown keyboard decode mode: {decode_mode!r}")
    else:
        effective_max_steps = max_steps

    offset = 0.0
    text: list[str] = list(initial_string)
    rows: list[dict[str, Any]] = []
    previous_action_ids = [action_count]
    previous_dt_values = [0.0]
    next_char_id_values: list[int] = []
    typo_rng = random.Random(typo_seed)
    timing_generator = None
    if timing_temperature > 0 and timing_seed is not None:
        timing_generator = torch.Generator(device=device)
        timing_generator.manual_seed(int(timing_seed))
    typos_used = 0
    learned_typo_prefixes: set[str] = set()
    with torch.no_grad():
        for _ in range(effective_max_steps):
            # Feed the model the current prefix history plus the next desired
            # target character. The next-char feature is a local guide, not a
            # hard action; the action head still decides what to do next.
            if decode_mode == "unconstrained":
                next_char = final_string[len(text)] if len(text) < len(final_string) else CHAR_EOS
            else:
                next_char = keyboard_next_char(final_string, text)
            next_char_id = char_to_id.get(next_char, char_to_id[CHAR_UNK])
            next_char_id_values.append(next_char_id)
            previous_action = torch.tensor([previous_action_ids], dtype=torch.long, device=device)
            previous_dt = torch.tensor([previous_dt_values], dtype=torch.float32, device=device)
            next_char_ids = torch.tensor([next_char_id_values], dtype=torch.long, device=device)
            dt_pred_all, logits_all, typo_logits_all, typo_action_logits_all, _ = model(
                final_ids,
                final_lengths,
                previous_action,
                previous_dt,
                next_char_ids,
            )
            dt_pred = dt_pred_all[:, -1:]
            logits = logits_all[:, -1:, :]
            typo_logit = typo_logits_all[0, -1] if typo_logits_all is not None else None
            typo_action_logits = typo_action_logits_all[0, -1] if typo_action_logits_all is not None else None

            if decode_mode in {"constrained", "canonical"}:
                action = ""
                action_id = -1
                step_kind = "target"
                current = "".join(text)
                if decode_mode == "canonical":
                    # Canonical mode is deterministic shortest-path editing. It
                    # still uses model timing, but not model action preferences.
                    action = constrained_keyboard_action(final_string, text)
                    action_id = int(action_to_id[action])
                    step_kind = "repair" if action == KEY_BACKSPACE else "target"
                else:
                    # Constrained mode lets the model choose among all reachable
                    # actions. The learned typo head is the only non-canonical
                    # correction strategy; it is also filtered through the same
                    # hard reachability mask as normal model actions.
                    remaining_steps_after_action = max(0, effective_max_steps - len(rows) - 1)
                    valid_action_ids = structured_keyboard_action_ids(
                        final_string=final_string,
                        text=text,
                        action_to_id=action_to_id,
                        remaining_steps_after_action=remaining_steps_after_action,
                    )
                    preferred_action = constrained_keyboard_action(final_string, text)
                    preferred_action_id = int(action_to_id[preferred_action])
                    learned_typo = None
                    selected_from_structured_head = False
                    if (
                        typo_logit is not None
                        and typo_action_logits is not None
                        and max_typos > 0
                        and typos_used < max_typos
                        and current not in learned_typo_prefixes
                        and final_string.startswith(current)
                        and current != final_string
                    ):
                        learned_typo = choose_learned_keyboard_typo(
                            typo_logit=typo_logit,
                            typo_action_logits=typo_action_logits,
                            valid_action_ids=valid_action_ids,
                            id_to_action=id_to_action,
                            preferred_action_id=preferred_action_id,
                            rng=typo_rng,
                            sample=sample,
                            temperature=temperature,
                            threshold=learned_typo_threshold,
                        )
                    if learned_typo is not None:
                        action, action_id, _ = learned_typo
                        typos_used += 1
                        learned_typo_prefixes.add(current)
                        step_kind = "learned_typo"
                    if not action:
                        action, action_id = choose_structured_keyboard_action(
                            logits[0, 0],
                            valid_action_ids=valid_action_ids,
                            id_to_action=id_to_action,
                            sample=sample,
                            temperature=temperature,
                            preferred_action_id=preferred_action_id,
                            preferred_bias=canonical_bias,
                        )
                        selected_from_structured_head = True
                    if selected_from_structured_head and action == KEY_STOP:
                        step_kind = "model_stop"
                    elif selected_from_structured_head and action == KEY_BACKSPACE:
                        step_kind = "model_repair"
                    elif (
                        selected_from_structured_head
                        and final_string.startswith(current)
                        and len(current) < len(final_string)
                        and action == final_string[len(current)]
                    ):
                        step_kind = "model_target"
                    elif selected_from_structured_head:
                        step_kind = "model_edit"
            elif sample:
                # Unconstrained mode is diagnostic: it samples or argmaxes the
                # raw action head and does not guarantee the target text.
                probs = torch.softmax(logits[0, 0] / max(temperature, 1e-4), dim=-1)
                action_id = int(torch.multinomial(probs, 1).item())
                action = id_to_action[action_id]
                step_kind = "sampled"
            else:
                action_id = int(logits[0, 0].argmax().item())
                action = id_to_action[action_id]
                step_kind = "model"

            dt_log = sample_timing_log(
                dt_pred[0, 0],
                timing_temperature,
                generator=timing_generator,
            )
            dt_ms = log_to_dt(float(dt_log.cpu()))
            if timing_temperature > 0:
                dt_ms = min(650.0, max(6.0, dt_ms))
            offset += dt_ms
            if action == KEY_STOP:
                # Stop is emitted only after the target is complete in
                # constrained/canonical modes, or whenever the raw model chooses
                # it in unconstrained mode.
                break

            apply_keyboard_action(text, action)
            rows.append(
                {
                    "offsetMs": offset,
                    "dtMs": dt_ms,
                    "action": action,
                    "textAfter": "".join(text),
                    "stepKind": step_kind,
                }
            )
            previous_action_ids.append(action_id)
            previous_dt_values.append(float(dt_log.detach().cpu()))

    # Constrained modes are intended for execution, so failing to reach the
    # requested text is an invariant violation rather than a soft metric.
    if decode_mode in {"constrained", "canonical"} and "".join(text) != final_string:
        budget_detail = ""
        if predicted_press_count is not None:
            budget_detail = (
                f" using predicted press budget {predicted_press_count:.2f} "
                f"with guard band {max(0, structured_extra_steps)}"
            )
        raise RuntimeError(
            f"{decode_mode.capitalize()} keyboard decode failed to reach target {final_string!r}; "
            f"ended at {''.join(text)!r} after {effective_max_steps} allowed steps{budget_detail}."
        )
    return rows


def decode_keyboard_rows(
    checkpoint: dict,
    model: KeyboardActionGRU,
    final_string: str,
    device: torch.device,
    max_steps: int,
    decode_mode: str = "constrained",
    sample: bool = False,
    temperature: float = 1.0,
    initial_string: str = "",
    structured_extra_steps: int = 6,
    canonical_bias: float = 3.0,
    max_typos: int = 2,
    typo_seed: int | None = 13,
    learned_typo_threshold: float = 0.2,
    timing_temperature: float = 0.0,
    timing_seed: int | None = None,
) -> list[dict[str, Any]]:
    """Compatibility wrapper around `KeyboardDecoder.decode`."""
    return KeyboardDecoder(checkpoint=checkpoint, model=model, device=device).decode(
        final_string=final_string,
        max_steps=max_steps,
        decode_mode=decode_mode,
        sample=sample,
        temperature=temperature,
        initial_string=initial_string,
        structured_extra_steps=structured_extra_steps,
        canonical_bias=canonical_bias,
        max_typos=max_typos,
        typo_seed=typo_seed,
        learned_typo_threshold=learned_typo_threshold,
        timing_temperature=timing_temperature,
        timing_seed=timing_seed,
    )
