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
    DEFAULT_KEYBOARD_TYPO_MODE_WEIGHTS,
    KEY_BACKSPACE,
    KEY_STOP,
    KEYBOARD_TYPO_MODE_ALIASES,
)
from .keyboard_logic import (
    apply_keyboard_action,
    constrained_keyboard_action,
    keyboard_next_char,
    minimum_terminal_edit_steps,
    terminal_edit_actions,
)
from .models.keyboard import KeyboardActionGRU
from .models.mouse import MouseTrajectoryGRU
from .types import KeyboardEditStep, MouseEpisode
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

    def decode(
        self,
        episode: MouseEpisode,
        max_steps: int,
        click_threshold: float,
        min_dt_ms: float,
        endpoint_guidance: bool = True,
        sample: bool = False,
        temperature: float = 1.0,
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
                dt_ms = log_to_dt(float(dt_pred[0, 0].cpu()))
                if rows:
                    dt_ms = max(dt_ms, min_dt_ms)
                offset += dt_ms

                rel_x = float(pos_pred[0, 0, 0].cpu())
                rel_y = float(pos_pred[0, 0, 1].cpu())
                if self.position_frame == "goal_relative_delta":
                    if endpoint_guidance:
                        remaining_steps = max(1, max_steps - step_index)
                        min_delta = (1.0 - state_along) / remaining_steps
                        state_along = min(1.0, state_along + max(rel_x, min_delta, 0.0))
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
                next_previous[0] = float(dt_pred[0, 0].detach().cpu())
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


def keyboard_typo_candidates(action_to_id: dict[str, int], desired_action: str) -> list[str]:
    """List plausible wrong-key actions for typo injection."""
    return [
        action
        for action in sorted(action_to_id)
        if action not in {desired_action, KEY_BACKSPACE, KEY_STOP}
    ]


def parse_keyboard_typo_mode_weights(weights: str | dict[str, float] | None) -> dict[str, float]:
    """Normalize typo mode weights from CLI/config input.

    Accepts either a dictionary or comma-separated text such as
    `"replace=0.5,forward=0.3,backtrack=0.2"`. Mode aliases are normalized and
    duplicate modes are summed.
    """
    # Typo behavior is optional and expressed as small named plans rather than
    # arbitrary bad edits. Normalize aliases once so generation can work with a
    # compact mode -> weight map.
    if weights is None:
        weights = DEFAULT_KEYBOARD_TYPO_MODE_WEIGHTS
    parsed: dict[str, float] = {}
    if isinstance(weights, dict):
        items = weights.items()
    else:
        items_list: list[tuple[str, str]] = []
        for raw_part in weights.split(","):
            part = raw_part.strip()
            if not part:
                continue
            if "=" in part:
                mode, value = part.split("=", 1)
                items_list.append((mode.strip(), value.strip()))
            else:
                items_list.append((part, "1.0"))
        items = items_list

    for raw_mode, raw_weight in items:
        mode = KEYBOARD_TYPO_MODE_ALIASES.get(str(raw_mode).strip().lower())
        if mode is None:
            allowed = ", ".join(sorted(set(KEYBOARD_TYPO_MODE_ALIASES.values())))
            raise ValueError(f"Unknown keyboard typo mode {raw_mode!r}; expected one of: {allowed}.")
        weight = float(raw_weight)
        if weight < 0:
            raise ValueError(f"Keyboard typo mode weights must be non-negative; got {raw_mode}={weight}.")
        parsed[mode] = parsed.get(mode, 0.0) + weight

    if sum(parsed.values()) <= 0:
        raise ValueError("At least one keyboard typo mode weight must be greater than zero.")
    return parsed


def weighted_keyboard_typo_mode(modes: list[tuple[str, float]], rng: random.Random) -> str | None:
    """Sample a typo mode from `(mode, weight)` pairs."""
    total = sum(weight for _, weight in modes)
    if total <= 0:
        return None
    pick = rng.random() * total
    cumulative = 0.0
    for mode, weight in modes:
        cumulative += weight
        if pick <= cumulative:
            return mode
    return modes[-1][0]


def choose_keyboard_typo(
    logits: torch.Tensor,
    action_to_id: dict[str, int],
    id_to_action: dict[int, str],
    desired_action: str,
    rng: random.Random,
    temperature: float,
) -> tuple[str, int] | None:
    """Sample a wrong keyboard action from model logits.

    The candidate set excludes the desired target action and structural repair
    tokens. Returns both the action string and id, or `None` if no wrong-key
    action exists in the checkpoint vocabulary.
    """
    # Wrong-key choices still come from the model distribution, just restricted
    # away from the desired action and repair/stop tokens. That keeps injected
    # typos shaped like actions the model considers plausible.
    candidates = keyboard_typo_candidates(action_to_id, desired_action)
    if not candidates:
        return None
    candidate_ids = torch.tensor([action_to_id[action] for action in candidates], dtype=torch.long, device=logits.device)
    candidate_logits = logits.index_select(0, candidate_ids)
    probs = torch.softmax(candidate_logits / max(temperature, 1e-4), dim=0).detach().cpu().tolist()
    pick = rng.random()
    cumulative = 0.0
    for candidate_id, probability in zip(candidate_ids.detach().cpu().tolist(), probs, strict=False):
        cumulative += float(probability)
        if pick <= cumulative:
            return id_to_action[int(candidate_id)], int(candidate_id)
    fallback_id = int(candidate_ids[-1].detach().cpu())
    return id_to_action[fallback_id], fallback_id


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


def apply_keyboard_plan(text: list[str], plan: list[KeyboardEditStep]) -> list[str]:
    """Apply a candidate edit plan to text and return the resulting text."""
    result = list(text)
    for step in plan:
        apply_keyboard_action(result, step.action)
    return result


def minimum_constrained_keyboard_steps(final_string: str, text: list[str]) -> int:
    """Return the minimum edits needed to finish a constrained keyboard target."""
    return minimum_terminal_edit_steps(final_string, text)


def sample_keyboard_typo_plan(
    logits: torch.Tensor,
    action_to_id: dict[str, int],
    id_to_action: dict[int, str],
    final_string: str,
    text: list[str],
    rng: random.Random,
    temperature: float,
    mode_weights: dict[str, float],
    max_wrong_chars: int,
    max_backtrack_chars: int,
) -> list[KeyboardEditStep]:
    """Build a bounded typo-and-repair plan for constrained keyboard decoding.

    Plans are small local detours: replace one target character, type extra
    wrong characters then repair them, or backtrack over already-correct text.
    The caller is responsible for checking that the resulting text can still be
    repaired within the decode step budget.
    """
    # A typo plan is a bounded detour around the normal target path. Each plan
    # must be repairable by later constrained decoding, so callers check the
    # resulting edit budget before committing to it.
    current = "".join(text)
    if not final_string.startswith(current) or current == final_string:
        return []

    modes: list[tuple[str, float]] = []
    if max_wrong_chars > 0:
        modes.extend(
            (mode, mode_weights.get(mode, 0.0))
            for mode in ("replace", "forward")
            if mode_weights.get(mode, 0.0) > 0
        )
    if text and max_backtrack_chars > 0 and mode_weights.get("backtrack", 0.0) > 0:
        modes.append(("backtrack", mode_weights["backtrack"]))

    mode = weighted_keyboard_typo_mode(modes, rng)
    if mode is None:
        return []

    desired_action = final_string[len(current)]
    if mode == "replace":
        typo = choose_keyboard_typo(
            logits,
            action_to_id=action_to_id,
            id_to_action=id_to_action,
            desired_action=desired_action,
            rng=rng,
            temperature=temperature,
        )
        if typo is None:
            return []
        wrong_action, _ = typo
        return [
            KeyboardEditStep(wrong_action, "replace"),
            KeyboardEditStep(KEY_BACKSPACE, "repair"),
            KeyboardEditStep(desired_action, "target"),
        ]

    if mode == "forward":
        wrong_count = rng.randint(1, max_wrong_chars)
        plan = [KeyboardEditStep(desired_action, "target")]
        for _ in range(wrong_count):
            typo = choose_keyboard_typo(
                logits,
                action_to_id=action_to_id,
                id_to_action=id_to_action,
                desired_action=desired_action,
                rng=rng,
                temperature=temperature,
            )
            if typo is None:
                return []
            wrong_action, _ = typo
            plan.append(KeyboardEditStep(wrong_action, "forward"))
        plan.extend(KeyboardEditStep(KEY_BACKSPACE, "repair") for _ in range(wrong_count))
        return plan

    if mode == "backtrack":
        backtrack_count = rng.randint(1, min(max_backtrack_chars, len(text)))
        return [KeyboardEditStep(KEY_BACKSPACE, "backtrack") for _ in range(backtrack_count)]

    return []


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
        canonical_bias: float = 1.5,
        typo_rate: float = 0.0,
        max_typos: int = 2,
        typo_seed: int | None = 13,
        typo_mode_weights: str | dict[str, float] | None = None,
        max_typo_chars: int = 3,
        max_backtrack_chars: int = 2,
        typo_min_dt_ms: float = 20.0,
        learned_typo_threshold: float = 0.2,
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
            typo_rate=typo_rate,
            max_typos=max_typos,
            typo_seed=typo_seed,
            typo_mode_weights=typo_mode_weights,
            max_typo_chars=max_typo_chars,
            max_backtrack_chars=max_backtrack_chars,
            typo_min_dt_ms=typo_min_dt_ms,
            learned_typo_threshold=learned_typo_threshold,
        )


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
    canonical_bias: float = 1.5,
    typo_rate: float = 0.0,
    max_typos: int = 2,
    typo_seed: int | None = 13,
    typo_mode_weights: str | dict[str, float] | None = None,
    max_typo_chars: int = 3,
    max_backtrack_chars: int = 2,
    typo_min_dt_ms: float = 20.0,
    learned_typo_threshold: float = 0.2,
) -> list[dict[str, Any]]:
    """Roll out keyboard edit rows from a trained keyboard checkpoint model.

    The returned rows contain cumulative `offsetMs`, per-key `dtMs`, the emitted
    action, resulting text, and a `stepKind` label. `constrained` mode masks the
    model to actions that can still reach `final_string`; `canonical` mode emits
    the shortest valid edit path while still using model timing; `unconstrained`
    mode exposes raw model action choices and may not reach the target. Optional
    typo settings inject bounded correction plans before returning to normal
    constrained decoding.
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
    if not 0.0 <= typo_rate <= 1.0:
        raise ValueError(f"typo_rate must be between 0 and 1, got {typo_rate}.")
    if max_typos < 0:
        raise ValueError(f"max_typos must be non-negative, got {max_typos}.")
    if max_typo_chars < 0:
        raise ValueError(f"max_typo_chars must be non-negative, got {max_typo_chars}.")
    if max_backtrack_chars < 0:
        raise ValueError(f"max_backtrack_chars must be non-negative, got {max_backtrack_chars}.")
    if typo_min_dt_ms < 0:
        raise ValueError(f"typo_min_dt_ms must be non-negative, got {typo_min_dt_ms}.")
    if not 0.0 <= learned_typo_threshold <= 1.0:
        raise ValueError(f"learned_typo_threshold must be between 0 and 1, got {learned_typo_threshold}.")
    parsed_typo_mode_weights = parse_keyboard_typo_mode_weights(typo_mode_weights)

    # Establish the decode contract up front. Constrained mode reserves a small
    # amount of extra room for learned repairs; canonical mode follows the
    # shortest path; unconstrained mode is raw logits and may miss the target.
    if decode_mode == "constrained":
        require_keyboard_target_supported(initial_string, final_string, action_to_id)
        min_steps = minimum_terminal_edit_steps(final_string, list(initial_string))
        effective_max_steps = min(max_steps, min_steps + max(0, structured_extra_steps))
        if max_steps < min_steps:
            raise SystemExit(
                f"Constrained keyboard decode needs at least {min_steps} steps for this target; "
                f"got --max-steps {max_steps}."
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
    final_ids, final_lengths = encode_keyboard_condition(initial_string, final_string, char_to_id, device)
    previous_action_ids = [action_count]
    previous_dt_values = [0.0]
    next_char_id_values: list[int] = []
    typo_rng = random.Random(typo_seed)
    typos_used = 0
    learned_typo_prefixes: set[str] = set()
    pending_typo_plan: list[KeyboardEditStep] = []
    with torch.no_grad():
        for _ in range(max_steps):
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
            dt_pred_all, logits_all, typo_logits_all, typo_action_logits_all = model(
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
                if pending_typo_plan:
                    # Once a typo plan starts, finish it exactly so the injected
                    # detour is internally coherent before returning to normal
                    # model-constrained decoding.
                    edit_step = pending_typo_plan.pop(0)
                    action = edit_step.action
                    action_id = int(action_to_id[action])
                    step_kind = edit_step.step_kind
                else:
                    action = ""
                    action_id = -1
                    step_kind = "target"
                    current = "".join(text)
                    if not action:
                        if decode_mode == "canonical":
                            # Canonical mode is deterministic shortest-path
                            # editing. It still uses model timing, but not model
                            # action preferences.
                            action = constrained_keyboard_action(final_string, text)
                            action_id = int(action_to_id[action])
                            step_kind = "repair" if action == KEY_BACKSPACE else "target"
                        else:
                            # Constrained mode lets the model choose among all
                            # reachable actions. The canonical action receives a
                            # small bias so the rollout stays efficient unless
                            # the model strongly prefers another valid edit.
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
                            elif (
                                typo_rate > 0
                                and max_typos > 0
                                and typos_used < max_typos
                                and final_string.startswith(current)
                                and current != final_string
                                and typo_rng.random() < typo_rate
                            ):
                                # Legacy forced typo plans remain available for
                                # debugging older checkpoints. Learned typo
                                # heads are preferred when present.
                                plan = sample_keyboard_typo_plan(
                                    logits[0, 0],
                                    action_to_id=action_to_id,
                                    id_to_action=id_to_action,
                                    final_string=final_string,
                                    text=text,
                                    rng=typo_rng,
                                    temperature=temperature,
                                    mode_weights=parsed_typo_mode_weights,
                                    max_wrong_chars=max_typo_chars,
                                    max_backtrack_chars=max_backtrack_chars,
                                )
                                plan_end_text = apply_keyboard_plan(text, plan)
                                required_steps = len(plan) + minimum_constrained_keyboard_steps(final_string, plan_end_text)
                                if plan and len(rows) + required_steps <= max_steps:
                                    typos_used += 1
                                    edit_step = plan.pop(0)
                                    pending_typo_plan.extend(plan)
                                    action = edit_step.action
                                    action_id = int(action_to_id[action])
                                    step_kind = edit_step.step_kind
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

            dt_ms = log_to_dt(float(dt_pred[0, 0].cpu()))
            if step_kind in {"replace", "forward", "backtrack", "repair"} and typo_min_dt_ms > 0:
                dt_ms = max(dt_ms, typo_min_dt_ms)
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
            previous_dt_values.append(float(dt_pred[0, 0].detach().cpu()))

    # Constrained modes are intended for execution, so failing to reach the
    # requested text is an invariant violation rather than a soft metric.
    if decode_mode in {"constrained", "canonical"} and "".join(text) != final_string:
        raise RuntimeError(
            f"{decode_mode.capitalize()} keyboard decode failed to reach target {final_string!r}; "
            f"ended at {''.join(text)!r} after {max_steps} steps."
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
    canonical_bias: float = 1.5,
    typo_rate: float = 0.0,
    max_typos: int = 2,
    typo_seed: int | None = 13,
    typo_mode_weights: str | dict[str, float] | None = None,
    max_typo_chars: int = 3,
    max_backtrack_chars: int = 2,
    typo_min_dt_ms: float = 20.0,
    learned_typo_threshold: float = 0.2,
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
        typo_rate=typo_rate,
        max_typos=max_typos,
        typo_seed=typo_seed,
        typo_mode_weights=typo_mode_weights,
        max_typo_chars=max_typo_chars,
        max_backtrack_chars=max_backtrack_chars,
        typo_min_dt_ms=typo_min_dt_ms,
        learned_typo_threshold=learned_typo_threshold,
    )
